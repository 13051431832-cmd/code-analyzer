public class UserService {

    private UserRepository repository;

    // Public method with return type
    public User findById(long id) {
        return repository.findById(id);
    }

    // Static method with void return
    public static void validate(User user) throws ValidationException {
        if (user == null) {
            throw new ValidationException("User cannot be null");
        }
    }

    // Private method with complex return type
    private Map<String, List<User>> groupByRole(List<User> users) {
        return users.stream().collect(Collectors.groupingBy(User::getRole));
    }

    // Method with throws clause
    public String fetchData(String url) throws IOException, InterruptedException {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder().uri(URI.create(url)).build();
        return client.send(request, BodyHandlers.ofString()).body();
    }

    // Final method
    public final int calculateScore(User user) {
        return user.getPosts().size() * 10;
    }

    // Interface default method
    public default String getDisplayName() {
        return this.name;
    }
}
